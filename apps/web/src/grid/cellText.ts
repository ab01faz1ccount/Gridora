import type { Cell } from "@contracts";
import { formatDate, formatNumber } from "@/i18n/format";
import type { Calendar, Digits, Locale } from "@/state/prefs";

export interface DisplayPrefs {
  digits: Digits;
  calendar: Calendar;
  locale: Locale;
  trueText: string;
  falseText: string;
}

export interface CellDisplay {
  text: string;
  kind: "empty" | "num" | "str" | "bool" | "err" | "date";
}

/**
 * Numbers with a number format show the text the server made (`Cell.d`: 1,234.50, 25% ...); the other
 * values show as they are. Look (font, colours) is applied by the grid from `Cell.s`, not here. The
 * chosen digit set applies to all numbers.
 */
const PERSIAN = "۰۱۲۳۴۵۶۷۸۹";
const ARABIC = "٠١٢٣٤٥٦٧٨٩";

/** Digits (and the separators between them) of server-made text in the chosen digit set. */
export function localizeDigits(text: string, digits: Digits): string {
  if (digits === "latin") return text;
  const set = digits === "persian" ? PERSIAN : ARABIC;
  return text
    .replace(/\d/g, (d) => set[Number(d)] ?? d)
    .replace(/(?<=[۰-۹٠-٩]),(?=[۰-۹٠-٩])/g, "٬")
    .replace(/(?<=[۰-۹٠-٩])\.(?=[۰-۹٠-٩])/g, "٫");
}

export function cellDisplay(cell: Cell | undefined, p: DisplayPrefs): CellDisplay {
  const v = cell?.v;
  if (!v) return { text: "", kind: "empty" };
  switch (v.k) {
    case "num":
      if (cell?.d) return { text: localizeDigits(cell.d, p.digits), kind: "num" };
      return { text: formatNumber(v.n, p.digits, 10, false), kind: "num" };
    case "str":
      return { text: v.s, kind: "str" };
    case "bool":
      return { text: v.b ? p.trueText : p.falseText, kind: "bool" };
    case "err":
      return { text: v.e, kind: "err" };
    case "date":
      return { text: formatDate(v.iso, p), kind: "date" };
  }
}
