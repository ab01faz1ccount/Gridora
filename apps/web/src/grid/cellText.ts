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
 * Raw display only. Cell styles and number formats (`Cell.s`, `Cell.t`) are NOT applied: no
 * contract exposes the style table yet (apps/PLAN.md 3.3). Numbers use the chosen digit set.
 */
export function cellDisplay(cell: Cell | undefined, p: DisplayPrefs): CellDisplay {
  const v = cell?.v;
  if (!v) return { text: "", kind: "empty" };
  switch (v.k) {
    case "num":
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
