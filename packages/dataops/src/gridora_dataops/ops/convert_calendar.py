"""convert_calendar: Gregorian <-> Jalali. Explicit only: nothing converts dates implicitly (I18N_SPEC).

Storage stays Gregorian. `to_jalali` turns a date column into text `YYYY/MM/DD` (or three integer columns);
`from_jalali` turns Jalali text (any digit script; `/`, `-`, `.` separators) into a real date.
Supported Jalali years: 1300..1500 (see persian/jalali.py); anything else is an unconvertible value.
"""
from __future__ import annotations

from typing import Literal, Optional

import polars as pl
from gridora_contracts.models import Warning_
from pydantic import Field

from ..errors import DataOpsError, pointer
from ..ops_common import unique_name
from ..persian.chars import variant_fold
from ..persian.jalali import MAX_YEAR, MIN_YEAR, format_jalali, from_jalali, to_jalali
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv, column_field


class CalendarParams(ParamsModel):
    has_header: bool = Field(True, json_schema_extra={"x-gridora-order": 0})
    column: str = column_field()
    direction: Literal["to_jalali", "from_jalali"] = "to_jalali"
    format: Literal["text", "parts"] = Field("text", json_schema_extra={
        "x-gridora-visible-if": {"property": "direction", "equals": "to_jalali"}})
    digits: Literal["persian", "latin"] = Field("persian", json_schema_extra={
        "x-gridora-persian-option": True, "x-gridora-visible-if": {"property": "direction", "equals": "to_jalali"}})
    output_column: Optional[str] = Field(None, max_length=200, json_schema_extra={"x-gridora-group": "ops.groups.advanced"})
    on_error: Literal["fail", "null"] = "fail"


_JALALI_TEXT = r"^(\d{3,4})/(\d{1,2})/(\d{1,2})$"


class ConvertCalendarOp(OperationSpec):
    type = "convert_calendar"
    category = "dates"
    destructive = True  # replaces the source column unless `output_column` is given
    Params = CalendarParams

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, CalendarParams)
        col = params.column
        dtype = frame.schema[col]
        src = frame[col]
        if params.direction == "to_jalali":
            if not (dtype == pl.Date or isinstance(dtype, pl.Datetime)):
                raise DataOpsError("type_mismatch", f"'{col}' is not a date column",
                                   path=pointer("params", "column"), hint="use change_type to make it a date first")
            dates = src.dt.date() if isinstance(dtype, pl.Datetime) else src
            parts = to_jalali(dates)
            bad = int((dates.is_not_null() & parts["year"].is_null()).sum())
            examples = [str(x) for x in dates.filter(dates.is_not_null() & parts["year"].is_null()).head(3).to_list()]
            if params.format == "text":
                new = [format_jalali(parts["year"], parts["month"], parts["day"], persian_digits=params.digits == "persian")
                       .alias(params.output_column or col)]
            else:
                base = params.output_column or col
                taken = set(frame.columns) - ({col} if params.output_column is None else set())
                names: list[str] = []
                for suffix in ("year", "month", "day"):
                    n = unique_name(f"{base}_{suffix}", taken | set(names))
                    names.append(n)
                new = [parts[k].alias(n) for k, n in zip(("year", "month", "day"), names, strict=True)]
        else:
            if dtype != pl.String:
                raise DataOpsError("type_mismatch", f"'{col}' is not text", path=pointer("params", "column"))
            text = frame.select(variant_fold(pl.col(col).str.strip_chars()).str.replace_all(r"[-.]", "/").alias("t"))["t"]
            m = text.str.extract_groups(_JALALI_TEXT)
            y, mo, d = (m.struct.field(str(i)).cast(pl.Int64, strict=False) for i in (1, 2, 3))
            dates = from_jalali(y, mo, d)
            nonblank = src.is_not_null() & (src.str.strip_chars() != "")
            bad = int((nonblank & dates.is_null()).sum())
            examples = [str(x) for x in src.filter(nonblank & dates.is_null()).head(3).to_list()]
            new = [dates.alias(params.output_column or col)]
        if bad and params.on_error == "fail":
            raise DataOpsError("type_mismatch", f"{bad} value(s) cannot be converted (supported Jalali years "
                               f"{MIN_YEAR}-{MAX_YEAR})", path=pointer("params", "column"), hint="e.g. " + "; ".join(examples))
        warnings = []
        if bad:
            warnings.append(Warning_(code="values_set_to_null", severity="warn", location=col,
                                     message=f"{bad} value(s) could not be converted and were left empty"))
        names = [s.name for s in new]
        i = frame.columns.index(col)
        # assemble: replace the source (or add next to it when output_column is given)
        cols = {c: frame[c] for c in frame.columns}
        order = list(frame.columns)
        if params.output_column is None:
            order[i:i + 1] = names
            cols.pop(col, None)
        else:
            clash = [n for n in names if n in cols]
            if clash:
                raise DataOpsError("invalid_param", f"a column named '{clash[0]}' already exists",
                                   path=pointer("params", "output_column"))
            order[i + 1:i + 1] = names
        for s in new:
            cols[s.name] = s
        out = pl.DataFrame([cols[n] for n in order])
        return OpOutput(out, warnings)
