import { usePrefs, type Locale } from "@/state/prefs";
import en from "./en.json";
import fa from "./fa.json";

export type MessageKey = keyof typeof fa;

// Compile-time catalog parity: `en` must have exactly the keys of `fa`.
const catalogs: Record<Locale, Record<MessageKey, string>> = { fa, en };

export const DIRECTION: Record<Locale, "rtl" | "ltr"> = { fa: "rtl", en: "ltr" };

export type Params = Record<string, string | number>;

export function translate(locale: Locale, key: MessageKey, params?: Params): string {
  const text = catalogs[locale][key];
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}

export function useT(): (key: MessageKey, params?: Params) => string {
  const locale = usePrefs((s) => s.locale);
  return (key, params) => translate(locale, key, params);
}

/** Keep <html lang/dir> in step with the UI language. */
export function applyDocumentLocale(locale: Locale): void {
  document.documentElement.lang = locale;
  document.documentElement.dir = DIRECTION[locale];
}

export const MESSAGE_KEYS = Object.keys(fa) as MessageKey[];
export { catalogs };
