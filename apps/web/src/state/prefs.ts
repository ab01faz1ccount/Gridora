// Display preferences (client-side only in v1; apps/PLAN.md 3.2). The ONLY place that touches
// localStorage, always guarded: storage can be empty, full or blocked.
import { create } from "zustand";

export type Locale = "fa" | "en";
export type Digits = "latin" | "persian" | "arabic";
export type Calendar = "gregorian" | "jalali";

export interface Prefs {
  locale: Locale;
  digits: Digits;
  calendar: Calendar;
}

const KEY = "gridora.prefs";
const DEFAULTS: Prefs = { locale: "fa", digits: "persian", calendar: "gregorian" };

const isOneOf = <T extends string>(v: unknown, allowed: readonly T[]): v is T =>
  typeof v === "string" && (allowed as readonly string[]).includes(v);

export function readPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...DEFAULTS };
    const p: unknown = JSON.parse(raw);
    if (typeof p !== "object" || p === null) return { ...DEFAULTS };
    const o = p as Record<string, unknown>;
    return {
      locale: isOneOf(o.locale, ["fa", "en"] as const) ? o.locale : DEFAULTS.locale,
      digits: isOneOf(o.digits, ["latin", "persian", "arabic"] as const) ? o.digits : DEFAULTS.digits,
      calendar: isOneOf(o.calendar, ["gregorian", "jalali"] as const) ? o.calendar : DEFAULTS.calendar,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

function writePrefs(p: Prefs): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(p));
  } catch {
    /* storage unavailable: the preference just lasts for this session */
  }
}

interface PrefsState extends Prefs {
  set: (patch: Partial<Prefs>) => void;
}

export const usePrefs = create<PrefsState>((set, get) => ({
  ...readPrefs(),
  set: (patch) => {
    set(patch);
    const { locale, digits, calendar } = get();
    writePrefs({ locale, digits, calendar });
  },
}));

/** Reload from storage (used by tests and when another tab changes the prefs). */
export function reloadPrefs(): void {
  usePrefs.setState(readPrefs());
}
