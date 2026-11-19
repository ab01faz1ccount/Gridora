# Design note: `suggest()` — operation suggestions from a column profile

**Status: design only (Review 5, order 3). No code. Whether and how to build it is the owner's decision (see "Decisions I need").**
Author: Agent 2. Audience: the owner (decides), Agent 0 (contracts), Agent 3 (UI).

## 1. What it is for
UX_SPEC puts "what do you want to do?" in front of the user. Today the user must already know the operation exists. `suggest()` closes the
gap from the other side: **look at the data they selected and offer the 1 to 5 operations that probably fix something visible in it**,
as chips next to the selection ("۱۲ ردیف تکراری پیدا شد · حذف تکراری‌ها"). One click opens the normal operation panel with the parameters
already filled and the normal live preview. Nothing is ever applied by `suggest()`.

Non-goals: no machine learning, no network call, no auto-apply, no change to the data, no suggestion text that the user could mistake for a
result. If the owner later wants LLM-written suggestions, that is a separate decision (data would leave the server) and a separate note.

## 2. Interface (proposal; needs a contract change, which is Agent 0's)
```
suggest(target: Target, ctx: ExecContext, selection: Selection | None = None, locale: str = "fa", limit: int = 5) -> list[Suggestion]

Selection   = { columns: list[str] | None, range: Range | None }      # what the user selected; None = the whole table/range
Suggestion  = {
  operation: str,            # an operation id from describe_all()
  params: dict,              # pre-filled and VALID: executor.validate(Operation(...)) == []
  title: str,                # Persian, from the catalog (key suggest.<rule>.title)
  reason: str,               # Persian sentence with the numbers ("۱۲ ردیف تکراری پیدا شد")
  evidence: { rule: str, count: int, share: float, examples: list[str] },   # examples: at most 3, each cut at 40 characters
  score: float,              # 0..1, only for ordering; never shown as a percentage
  destructive: bool,         # copied from the operation's descriptor
}
```
Read-only: same permission as `preview`. Raises nothing for "nothing to suggest" (returns `[]`).

## 3. The profile (what the rules look at)
Computed with one Polars pass over the selected columns (plus the table-level numbers). All shares are over non-empty cells unless stated.

| Level | Fact | How it is measured |
|---|---|---|
| table | rows, columns, **duplicate-row share**, blank-row share, formula-cell count (sheets) | `is_duplicated`, all-null rows, `SheetFrame.formula_cells` |
| column | logical type, empty share, distinct count (exact up to 1M rows, else approximate), constant?, key-like? (distinct == rows) | Polars |
| column (text) | share with leading/trailing spaces; share with runs of spaces; share containing Arabic ي/ك; share containing ZWNJ; share with tatweel/diacritics | same character tables as `clean_text` |
| column (text) | **digit scripts present** (Persian / Arabic-Indic / Latin) and whether they are mixed | `persian/chars.py` |
| column (text) | share that parses as a **number** (with the `change_type` rules: Persian digits, ٬ separators); as an ISO/slashed **date**; as a **Jalali date** in 1300-1500 | the real converters, so a suggestion can never promise a conversion that would fail |
| column (text) | most common **delimiter** (`,` `;` `|` `-` space) and the share of cells where it splits into 2 to 6 parts | counting |
| column | **sorted state** (ascending / descending / none) | adjacent comparison |
| column | fill-down pattern: empty share between 10% and 90% and non-empty values appear in runs | run lengths |
| header names | matches a small Persian glossary (نام، نام خانوادگی، ماه‌ها، فروردین ...) | exact + variant-folded match |
| table | several columns with the same type and month/year-like names ("wide" table) | glossary |

Sampling: a table is profiled in full up to 1,000,000 cells; above that, a seeded sample of 100,000 rows (and `sampled: true` in the evidence, so the sentence can say
"در نمونه‌ی ۱۰۰٬۰۰۰ ردیفی"). A sheet range is bounded by the 200,000-cell cap anyway and is read through the columnar path. A profile is cached per
`(table_id, version)` or `(range, document seq)`; it is never stored with the user's values. Budget (to be measured, not promised): under 300 ms for 100,000 x 20.

## 4. Rules (initial thresholds are guesses to be tuned on a corpus)
| # | Rule (fires when) | Suggests | Pre-filled parameters | Reason sentence (fa) | Guard against a bad suggestion |
|---|---|---|---|---|---|
| R1 | at least 1 duplicate row | `remove_duplicates` | `columns` = selected columns or none (= all) | «{n} ردیف تکراری پیدا شد» | not if the selection is one key-like column |
| R2 | at least 1 cell with edge or double spaces | `clean_text` | `trim`, `collapse_spaces` | «{n} خانه فاصله‌ی اضافه دارد» | |
| R3 | at least 1 Arabic ي/ك | `clean_text` | `arabic_letters_to_persian` | «{n} خانه «ی» یا «ک» عربی دارد» | |
| R4 | two or more digit scripts in one column | `clean_text` | `digits` = the majority script | «ارقام این ستون ترکیبی از چند نوع است» | |
| R5 | text column, at least 80% parses as a number | `change_type` | `to` = `int64` or `float64` (decided by the data) | «{share}٪ این ستون عدد است ولی متن ذخیره شده» | not if the column name looks like an id/phone/code («کد», «تلفن») |
| R6 | text column, at least 80% parses as a date | `change_type` | `to` = `date` | «این ستون تاریخ است ولی متن ذخیره شده» | |
| R7 | at least 80% looks like a Jalali date (1300-1500) | `convert_calendar` (`from_jalali`) | `column` | «این ستون تاریخ شمسی است؛ می‌توانید به میلادی تبدیل کنید» | |
| R8 | fill-down pattern | `fill` | `mode=down`, the column | «{n} خانه‌ی خالی بین مقدارهای تکراری دارید» | |
| R9 | at least 80% of cells split into 2 to 6 parts by the same delimiter | `split_column` | `delimiter` | «این ستون چند مقدار با «{d}» جدا شده» | not for a sentence-like text (many spaces and long) |
| R10 | two neighbouring text columns whose names match the name glossary | `merge_columns` | the two columns, separator space | «می‌توانید نام و نام خانوادگی را یکی کنید» | low score |
| R11 | a number column and a low-distinct text column are both selected | `group_aggregate` | `by` = the text column, `sum` of the number | «جمع {ستون} را برای هر {ستون دسته} حساب کنید» | |
| R12 | wide table (six or more same-type columns with month/year-like names) | `unpivot` | `id_columns` = the others | «ماه‌ها ستون جدا هستند؛ می‌توانید زیر هم بیاورید» | low score |
| R13 | column not sorted, column selected | `sort` | the column, ascending | «این ستون مرتب نیست» | only if no rule above fired for the same column; never when already sorted |
| R14 | mixed number/text column | `change_type` | `to=string` | «این ستون هم عدد دارد هم متن» | |

Ranking: `score = rule confidence x impact x relevance`. Impact grows with the share of affected cells (log-scaled, so one bad cell in a
million rows does not beat 12 duplicate rows in a hundred), relevance is 1 for a selected column and 0.6 for others. At most 2 suggestions per
operation, at most `limit` in total; ties are broken by operation id, so the answer is deterministic. A candidate whose `preview_with_effect`
says `no_change` is dropped (checked only for the top candidates, so cost stays bounded). Dismissed suggestions are remembered by the client
per (user, rule, column name) and not shown again; the server stays stateless.

## 5. What it needs from other modules
- **Contracts (Agent 0):** an `OperationExecutor.suggest(...)` (or a separate `SuggestionService` protocol), `Selection`, `Suggestion`; an endpoint
  `POST /documents/{id}/suggestions`. `PreviewResult`/`OperationResult` are unaffected.
- **Catalog:** `suggest.<rule>.title` and `suggest.<rule>.reason` keys in `fa.json` (templates with `{n}`, `{share}`, `{d}`), Persian first.
- **UI (Agent 3):** chips near the selection, each showing the reason sentence; a click opens the operation panel with `params` filled.
- **Dataops internals:** a `profile.py` (pure functions over a Polars frame, no I/O), a `rules.py` (data, not code paths: one row per rule), reuse of `conversions.py` and `persian/chars.py`.

## 6. How I would test it
- Rule tests on small hand-built frames, each with a case that must fire and a case that must not.
- Every suggestion's `params` must pass `validate()` and `preview_with_effect` must not say `no_change` (property test over generated frames).
- Determinism (same input, same order), the examples cap (3 values, 40 characters) and that no example appears for a column the user did not select.
- A **corpus of messy Persian tables** (real-looking, with the usual mistakes) with the expected top suggestion per table; the target is a number agreed with the owner (I suggest: the right operation is in the top 3 for at least 80% of the curated cases, and fewer than 1 wrong chip per 5 selections on clean data). I will report the measured numbers, not the target.
- Performance on 100,000 x 20 with the budget above; mutation checks on the thresholds.

## 7. Risks
- **Noise** is the main risk: a chip that is wrong teaches users to ignore all chips. That is why every rule has a guard, why the list is capped at 5, and why dismissal is remembered.
- Number-like ids and phone numbers look like numbers (R5): the name guard helps but is a heuristic.
- The glossary (R10, R12) is Persian-only and small; it will miss names in other wording.
- A profile reads the user's data. It does so in the same process and with the same permission as `preview`; nothing is stored or logged, and `examples` is the only place values leave the profile.

## 8. Decisions I need (owner)
1. Build it at all, and when? (My estimate: profiler + R1 to R7 is a small-to-medium task; the rest, the ranking and the corpus evaluation take longer than the rules themselves.)
2. Run on selection automatically, or only when the user opens the "what do you want to do?" box? (Automatic is more helpful and more noisy and costs a profile per selection.)
3. Thresholds (80%, 1 duplicate row, the top-3 target): are these the right trade-off between helpful and annoying?
4. Where is "dismissed" stored: in the browser only (simple) or per account on the server?
5. May suggestions mention values from the user's data (the 3 examples), or only counts? (Counts only is safer for shared screens.)
6. Should chart suggestions (R11 is close to one) belong here or to the chart UI?
