import { ERROR_CODES } from "@contracts";
import type { MessageKey } from "@/i18n";
import { ApiError } from "./client";

const KNOWN = new Set<string>([...ERROR_CODES, "network"]);

/** Catalog key for an error. Unknown codes fall back to a generic message, never to raw text. */
export function errorKey(e: unknown): MessageKey {
  if (e instanceof ApiError && KNOWN.has(e.code)) return `error.${e.code}` as MessageKey;
  return "error.generic";
}
