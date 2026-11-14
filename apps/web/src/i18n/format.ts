// Number/date display and numeric input normalization (docs/I18N_SPEC.md).
// Stored and wire values are always Latin digits; digits and calendar are DISPLAY choices.
import type { Calendar, Digits } from "@/state/prefs";

const NUMBERING: Record<Digits, string> = { latin: "latn", persian: "arabext", arabic: "arab" };

export function formatNumber(n: number, digits: Digits, maximumFractionDigits = 10): string {
  const locale = digits === "latin" ? "en" : "fa-IR";
  return new Intl.NumberFormat(locale, {
    numberingSystem: NUMBERING[digits],
    maximumFractionDigits,
  }).format(n);
}

export function formatDate(
  iso: string,
  opts: { calendar: Calendar; digits: Digits; locale: "fa" | "en" },
): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const base = opts.locale === "fa" ? "fa-IR" : "en";
  const cal = opts.calendar === "jalali" ? "persian" : "gregory";
  const tag = `${base}-u-ca-${cal}-nu-${NUMBERING[opts.digits]}`;
  return new Intl.DateTimeFormat(tag, { dateStyle: "medium", timeZone: "UTC" }).format(d);
}

const DIGIT_MAP: Record<string, string> = {};
"۰۱۲۳۴۵۶۷۸۹".split("").forEach((ch, i) => (DIGIT_MAP[ch] = String(i)));
"٠١٢٣٤٥٦٧٨٩".split("").forEach((ch, i) => (DIGIT_MAP[ch] = String(i)));

/**
 * Turns "۱٬۲۳۴٫۵" (Persian/Arabic digits and separators) into "1234.5" so it can be sent to the
 * server. Only strings that are numbers after mapping are changed: formulas (leading "=") and
 * ordinary text are returned untouched, so digits inside words or formulas are never rewritten.
 */
export function normalizeNumericInput(input: string): string {
  const s = input.trim();
  if (s === "" || s.startsWith("=")) return input;
  let mapped = s
    .replace(/[۰-۹٠-٩]/g, (c) => DIGIT_MAP[c] ?? c)
    .replace(/٫/g, ".") // Arabic decimal separator
    .replace(/٬/g, ",") // Arabic thousands separator
    .replace(/[−–]/g, "-"); // typographic minus
  // Commas are only dropped when they are clearly thousands groups ("1,234,567.5"); "1,5" is
  // ambiguous, so it is left alone and the server reports it instead of guessing.
  if (/^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$/.test(mapped)) mapped = mapped.replace(/,/g, "");
  return /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(mapped) ? mapped : input;
}
