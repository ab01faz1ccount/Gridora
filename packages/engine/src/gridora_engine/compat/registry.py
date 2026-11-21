"""Compatibility feature registry (PLAN.md §6).

Honesty gate: an entry with tier "supported" or "partial" must list fixtures (or "generated"
for fixtures built inside the tests) and at least one test; tests/unit/test_registry.py checks
that those tests exist. Tier -> contract mapping: supported->supported, partial->partial,
preserved->unsupported(preserved=True), unsupported->unsupported.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Tier = Literal["supported", "partial", "preserved", "unsupported"]


@dataclass(frozen=True)
class Feature:
    code: str
    tier: Tier
    handling: str
    message: str  # may contain {count}
    tests: tuple[str, ...] = ()
    fixtures: tuple[str, ...] = ("generated",)
    editable: bool = True


_FEATURES = (
    Feature(
        "csv.encoding_guessed", "partial", "decoded with a guessed encoding",
        "The text encoding was guessed ({count} file); check that text looks right.",
        tests=("test_windows1256_detected_and_reported", "test_latin_fallback_is_reported"),
    ),
    Feature(
        "csv.delimiter_detected", "partial", "delimiter chosen automatically",
        "The delimiter was detected automatically.",
        tests=("test_delimiter_detection",),
    ),
    Feature(
        "csv.persian_digits_normalized", "partial", "Persian/Arabic-Indic digits converted",
        "{count} numeric fields written in Persian or Arabic-Indic digits were converted to numbers.",
        tests=("test_persian_digits_become_numbers",),
    ),
    Feature(
        "csv.numeric_like_kept_as_text", "partial", "kept as text to avoid data loss",
        "{count} number-like fields (leading zero, leading +, or more than 15 digits) "
        "were kept as text.",
        tests=("test_identifiers_stay_text",),
    ),
    Feature(
        "csv.formula_text_neutralized", "partial", "prefixed with an apostrophe on export",
        "{count} text cells starting with = + - @ were prefixed with ' to prevent formula "
        "injection when the CSV is opened in a spreadsheet.",
        tests=("test_export_neutralizes_formula_text",),
    ),
)
_PRESERVED_T = ("test_import_report_lists_preserved_parts_with_locations",)


def _pres(code: str, message: str, tests: tuple[str, ...] = _PRESERVED_T) -> Feature:
    return Feature(code, "preserved", "kept as original bytes; not read, shown or edited", message, tests=tests, editable=False)


_XLSX = (
    _pres("xlsx.vba_project", "Macros (VBA) are kept in the file but never run, shown or edited.",
          ("test_xlsm_macro_workbook_preserved_not_run",)),
    _pres("xlsx.pivot_table", "{count} pivot table part(s) are kept but not shown or edited; they may become stale if their source cells change."),
    _pres("xlsx.chart", "{count} chart(s) are kept but not shown or edited; they may become stale if their source cells change."),
    _pres("xlsx.drawing", "{count} drawing part(s) (shapes, images, chart anchors) are kept but not shown or edited."),
    _pres("xlsx.image", "{count} embedded image file(s) are kept but not shown."),
    _pres("xlsx.external_link", "{count} link(s) to other workbooks are kept, never followed; cached values are shown."),
    _pres("xlsx.custom_xml", "{count} custom XML part(s) are kept unchanged."),
    _pres("xlsx.comments", "{count} comment part(s) are kept but not shown or edited."),
    _pres("xlsx.threaded_comments", "{count} threaded-comment part(s) are kept but not shown or edited."),
    _pres("xlsx.table", "{count} Excel table definition(s) are kept; structured references are not interpreted."),
    _pres("xlsx.slicer", "{count} slicer part(s) are kept but not shown or edited."),
    _pres("xlsx.connections", "Data connections / query tables are kept but never refreshed."),
    _pres("xlsx.embedded_object", "{count} embedded object(s) are kept but not shown or opened."),
    _pres("xlsx.chartsheet", "{count} chart or dialog sheet(s) are kept but not listed as grids."),
    _pres("xlsx.workbook_protection", "Workbook structure protection is kept; Gridora does not enforce it."),
    _pres("xlsx.sheet_protection", "{count} sheet(s) have protection settings; they are kept, Gridora does not enforce them.",
          ("test_sheet_level_features_reported",)),
    _pres("xlsx.merged_cells", "{count} merged range(s) are kept but not shown or edited.", ("test_sheet_level_features_reported",)),
    _pres("xlsx.conditional_format", "{count} conditional-format rule block(s) are kept but not shown or edited.", ("test_sheet_level_features_reported",)),
    _pres("xlsx.data_validation", "{count} data-validation rule(s) are kept but not enforced.", ("test_sheet_level_features_reported",)),
    _pres("xlsx.auto_filter", "{count} sheet auto-filter(s) are kept but not shown or applied.", ("test_sheet_level_features_reported",)),
    _pres("xlsx.hyperlinks", "{count} sheet(s) contain hyperlinks; they are kept but not shown.", ("test_sheet_level_features_reported",)),
    _pres("xlsx.ext_list", "{count} extension block(s) of newer Excel features are kept unchanged.", ("test_sheet_level_features_reported",)),
    Feature("xlsx.defined_name", "partial", "read and kept; not editable",
            "{count} defined name(s) are read and kept; they cannot be edited yet.",
            tests=("test_rtl_frozen_hidden_and_defined_names",), editable=False),
    Feature("xlsx.full_calc_on_load", "partial", "setting kept; Gridora does not recalculate",
            "The file asks Excel to recalculate everything when it opens; the setting is kept.",
            tests=("test_full_calc_on_load_flag_is_reported",)),
    Feature("xlsx.rtl_view", "supported", "read and kept",
            "{count} sheet(s) use a right-to-left view; it is read and kept.",
            tests=("test_rtl_frozen_hidden_and_defined_names",)),
    Feature("xlsx.frozen_panes", "supported", "read and kept",
            "{count} sheet(s) have frozen panes; they are read and kept.",
            tests=("test_rtl_frozen_hidden_and_defined_names",)),
    Feature("xlsx.formulas_not_recalculated", "partial", "formula text and cached values shown",
            "About {count} formula cell(s): formulas and their saved results are shown, but Gridora cannot recalculate them yet.",
            tests=("test_import_values_types_dates_formulas_styles",)),
    Feature("xlsx.shared_formula", "partial", "cached values shown; dependent formula text not shown",
            "About {count} shared formula group(s): dependent cells show saved results but not their formula text; cells that belong to a group cannot be edited yet.",
            tests=("test_rich_text_and_shared_array_formulas",)),
    Feature("xlsx.array_formula", "partial", "formula text and cached values shown",
            "About {count} array formula(s) are shown with saved results; cells inside an array range cannot be edited yet.",
            tests=("test_rich_text_and_shared_array_formulas",)),
    Feature("xlsx.dynamic_array", "partial", "cached values shown",
            "About {count} cell(s) use dynamic-array or rich-value metadata; saved results are shown, spill ranges are not interpreted.",
            tests=("test_rich_text_and_shared_array_formulas",)),
    Feature("xlsx.rich_text", "partial", "shown as plain text; run formatting kept unless the cell is edited",
            "{count} cell text(s) have mixed formatting; they are shown as plain text and editing one loses its formatting.",
            tests=("test_rich_text_and_shared_array_formulas",)),
    Feature("xlsx.lazy_fallback", "partial", "slower full parse used",
            "{count} sheet(s) use markup that needs a slower full read; results are the same.",
            tests=("test_index_hint_is_validated_and_falls_back", "test_prefixed_namespace_sheet_uses_eager_path")),
    Feature("xlsx.cell_value_invalid", "partial", "invalid values replaced by #VALUE!",
            "{count} cell(s) had values that could not be read and are shown as #VALUE!.",
            tests=("test_invalid_cell_values_become_errors_and_are_recorded_as_findings",)),
    Feature("xlsx.error_value.unmapped", "partial", "shown as #VALUE!",
            "{count} cell(s) contain an error kind that is shown as #VALUE!; the file keeps the original.",
            tests=("test_invalid_cell_values_become_errors_and_are_recorded_as_findings",)),
    Feature("xlsx.cached_values_stale", "partial", "saved results kept; Excel recalculates on open",
            "Cells were edited and Gridora recalculated what it can, but {count} formula cell(s) could not be recalculated (unsupported function, data table, damaged formula or they depend on one): their saved results may be out of date until Excel recalculates.",
            tests=("test_unrecalculable_formulas_are_reported_as_stale",)),
    Feature("formula.unsupported_function", "partial", "saved result kept",
            "{count} formula cell(s) use a function Gridora cannot calculate yet; their saved results were kept.",
            tests=("test_unrecalculable_formulas_are_reported_as_stale",)),
    Feature("formula.circular", "partial", "saved result kept",
            "{count} formula cell(s) are part of a circular reference; their saved results were kept.",
            tests=("test_circular_formulas_are_reported",)),
    Feature("formula.calendar_mode", "partial", "date functions follow the workbook calendar",
            "{count} formula(s) use date functions while the calendar is not Gregorian: YEAR, MONTH, DAY, DATE, EDATE, EOMONTH, DATEDIF, DATEVALUE and TEXT read and write dates in that calendar, so results differ from Excel's Gregorian results.",
            tests=("test_calendar_mode_is_reported_for_date_formulas",)),
    Feature("xlsx.full_calc_on_load_set", "partial", "fullCalcOnLoad set in workbook.xml",
            "Excel is asked to recalculate all formulas when it opens the exported file.",
            tests=("test_edit_in_workbook_with_formulas_reports_stale_values_and_sets_full_calc",)),
    Feature("xlsx.calc_chain_dropped", "partial", "calcChain removed with its relationship and content type",
            "The calculation chain was removed because formulas changed; Excel rebuilds it.",
            tests=("test_calc_chain_is_dropped_only_when_formulas_change",)),
    Feature("xlsx.inline_strings", "partial", "edited text written as inline strings",
            "{count} edited text cell(s) are stored as inline strings; Excel converts them when the file is next saved.",
            tests=("test_edited_text_is_written_as_inline_string_and_roundtrips",)),
    Feature("xlsx.table.edited_inside", "partial", "table definition kept unchanged",
            "{count} Excel table(s) contain edited cells; the table definition was not changed.",
            tests=("test_edits_inside_preserved_part_sources_are_reported",), editable=False),
    Feature("xlsx.pivot_table.source_edited", "partial", "pivot cache kept unchanged",
            "{count} pivot cache(s) have edited source cells and may be out of date until refreshed in Excel.",
            tests=("test_edits_inside_preserved_part_sources_are_reported",), editable=False),
    Feature("xlsx.chart.source_edited", "partial", "chart kept unchanged",
            "{count} chart(s) use edited cells; Excel redraws them from the new values.",
            tests=("test_edits_inside_preserved_part_sources_are_reported",), editable=False),
    Feature("xlsx.preserved_parts_not_assessed", "partial", "not analyzed",
            "{count} preserved part(s) refer to data by name; whether edits affect them was not assessed.",
            tests=("test_edits_inside_preserved_part_sources_are_reported",), editable=False),
    Feature("xlsx.macro_enabled_extension", "partial", "main content type kept",
            "The workbook contains macros; save the exported file with the .xlsm extension or Excel will not open it.",
            tests=("test_xlsm_export_keeps_vba_and_says_to_use_xlsm_extension",)),
    Feature("xlsx.generated_from_csv", "partial", "new workbook written from the data",
            "The workbook was created from a CSV file: it has one default style and no formulas or number formats.",
            tests=("test_csv_workbook_exports_as_new_xlsx",)),
)
REGISTRY: dict[str, Feature] = {f.code: f for f in (*_FEATURES, *_XLSX)}
