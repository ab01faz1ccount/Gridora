// "What do you want to do?" search (docs/UX_SPEC.md 3.1): finds operations by the words a newcomer
// would type, using the label, description and the Persian task phrases of the catalog.
import type { OperationDescriptor } from "@contracts";

const DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩";

/** Same word, same letters: ي/ك to ی/ک, any digit script to Latin, no ZWNJ, tatweel or diacritics. */
export function normalizeText(s: string): string {
  let out = "";
  for (const ch of s.normalize("NFKC")) {
    const p = DIGITS.indexOf(ch);
    const a = ARABIC_DIGITS.indexOf(ch);
    if (p >= 0) out += String(p);
    else if (a >= 0) out += String(a);
    else if (ch === "ي" || ch === "ى") out += "ی";
    else if (ch === "ك") out += "ک";
    else if (ch === "‌" || ch === "‍" || ch === "ـ") continue;
    else if (/[ً-ٰٟ]/.test(ch)) continue;
    else out += ch;
  }
  return out.toLowerCase().replace(/\s+/g, " ").trim();
}

export interface OpEntry {
  type: string;
  label: string;
  description: string;
  category: string;
  destructive: boolean;
  keywords: string[];
  descriptor: OperationDescriptor;
}

const text = (catalog: Record<string, string>, key: string): string => catalog[key] ?? "";

/** Catalog keys: ops.<type>.label / .description / .keywords, ops.categories.<category>. */
export function opEntries(descriptors: OperationDescriptor[], catalog: Record<string, string>): OpEntry[] {
  return descriptors.map((d) => ({
    type: d.type,
    label: text(catalog, d.label) || text(catalog, `ops.${d.type}.label`) || d.type,
    description: text(catalog, d.description) || text(catalog, `ops.${d.type}.description`),
    category: text(catalog, `ops.categories.${d.category}`) || d.category,
    destructive: d.destructive,
    keywords: text(catalog, `ops.${d.type}.keywords`).split(/[،,;\n]/).map((k) => k.trim()).filter(Boolean),
    descriptor: d,
  }));
}

/** Higher is better; 0 means no match. Every word of the query must match somewhere. */
export function scoreEntry(e: OpEntry, query: string): number {
  const words = normalizeText(query).split(" ").filter(Boolean);
  if (words.length === 0) return 0;
  const label = normalizeText(e.label);
  const kws = e.keywords.map(normalizeText);
  const rest = normalizeText(`${e.description} ${e.category}`);
  let total = 0;
  for (const w of words) {
    let best = 0;
    if (label === w) best = 10;
    else if (label.includes(w)) best = 8;
    for (const k of kws) {
      if (k === w) best = Math.max(best, 9);
      else if (k.includes(w) || (w.length >= 3 && w.includes(k) && k.length >= 3)) best = Math.max(best, 6);
    }
    if (best === 0 && rest.includes(w)) best = 2;
    if (best === 0) return 0;
    total += best;
  }
  return total;
}

export function searchOps(entries: OpEntry[], query: string): OpEntry[] {
  if (normalizeText(query) === "") return entries;
  return entries
    .map((e) => ({ e, s: scoreEntry(e, query) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s || a.e.label.localeCompare(b.e.label, "fa"))
    .map((x) => x.e);
}
